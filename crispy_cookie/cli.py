#!/usr/bin/env python3
"""Console script for crispy_cookie."""

import json
import re
import sys
from argparse import ArgumentParser, FileType
from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from cookiecutter.environment import Environment, StrictEnvironment
from cookiecutter.generate import generate_files
from cookiecutter.prompt import prompt_for_config, render_variable
from cookiecutter.vcs import clone

from . import __version__
from .core import TemplateCollection, TemplateError, TemplateInfo

HIDDEN_VAR = re.compile(r"^_.*")

DO_NOT_INHERIT = [
    HIDDEN_VAR,
]


def dict_without_keys(d: dict, *keys):
    """ Return a copy of dict d without the given set of keys """
    d = dict(d)
    for key in keys:
        if hasattr(key, "match"):
            for k in list(d):
                if key.match(k):
                    del d[k]
        elif key in d:
            del d[key]
    return d


def move_to_layers(root, layer_name, folders_to_layer):
    for folder in folders_to_layer:
        folder = root / folder
        if folder.is_dir():
            # XXX: This fails if the directory already has a "suffix".  Does this happen?
            folder_d = folder.with_suffix(".d")
            layer_dest = folder_d / layer_name
            msg = "Layer move:  {} -> {}  ".format(folder, layer_dest)
            folder_d.mkdir()
            folder.replace(layer_dest)


def do_list(template_collection: TemplateCollection, args):
    print("Known templates:")
    for n in template_collection.list_templates():
        print(n)


def do_config(template_collection: TemplateCollection, args):
    layer_count = Counter()
    doc = {}
    layers = doc["layers"] = []
    print(f"Processing templates named:  {args.templates}")

    templates = args.templates[:]
    extends = set()
    for template_name in args.templates:
        tmp = template_collection.get_template(template_name)
        extends.update(tmp.extends)

    for template_name in extends:
        templates.insert(0, template_name)

    if args.templates != templates:
        print(f"Template list expanded to:  {templates}")

    shared_args = {}

    layer_mounts = doc["layer_mounts"] = []

    for template_name in templates:
        print(f"*** Handing template {template_name} ***")
        tmp = template_collection.get_template(template_name)
        layer_count[tmp.name] += 1
        n = layer_count[tmp.name]
        context = dict(tmp.default_context)
        layer_name = tmp.default_layer_name
        if n > 1:
            layer_name += f"-{n}"

        layer_mounts.extend(l for l in tmp.default_layer_mounts
                            if l not in layer_mounts)
        '''
        # Prompt user
        layer_name_prompt = input(f"Layer name?  [{layer_name}] ")
        if layer_name_prompt:
            layer_name = layer_name_prompt
        '''
        print(f"{template_name} {n}:  layer={layer_name}"
              #      f"  Context:  {context}"
              )
        layer = {
            "name": tmp.name,
            "layer_name": layer_name,
            "cookiecutter": context,
        }

        cc_context = {"cookiecutter": context}

        cc_inherited = {}
        # Apply inherited variables
        for var in tmp.inherits:
            if var in shared_args:
                # Block from prompting for this var
                value = shared_args[var]
                cc_inherited[var] = value
                print(f"   Inheriting {var}={value}")
                cc_context["cookiecutter"][var] = value
            else:
                print(f"   Missing inherited {var}.  Will prompt")

        # No need to prompt for ephemeral cookiecutter variables
        for var in tmp.ephemeral:
            print(f"   Skipping prompt for {var} as it is ephemeral")
            cc_context["cookiecutter"].pop(var, None)

        # XXX: Should we also skip prompting for inherited variables?

        # Prompt the user
        final = prompt_for_config(cc_context)

        layer["cookiecutter"] = dict_without_keys(final, HIDDEN_VAR)
        layer["layer_name"] = final["layer"]

        # Update shared args for next layer to inherit from
        shared_args.update(dict_without_keys(final, *DO_NOT_INHERIT))

        # Remove any inherited variables that were NOT updated, and allow them
        # to be inherited at 'build' time.  Reduces redundancy in crispycookie.json
        for key, value in cc_inherited.items():
            if layer["cookiecutter"][key] == value:
                # print(f"   Cleaning out redundant {key}={value} for this layer")
                del layer["cookiecutter"][key]

        layers.append(layer)
        print("")

    json.dump(doc, args.output, indent=4)


def no_print(*a, **kw):
    pass


_print = print


def is_template(value):
    try:
        return "{{" in value
    except TypeError:
        return False


def nested_expand_missing(data: dict, context: dict, template: TemplateInfo,
                          inherited_vars: dict, env: Environment, path=()):
    if isinstance(data, dict):
        output = {}
        for (key, value) in data.items():
            if is_template(key):
                old_key = key
                key = render_variable(env, key, context)
                print("Expanding {old_key} to {key}")
            value = nested_expand_missing(value, context, template, inherited_vars, env, path + (key,))
            output[key] = value
        return output
    elif isinstance(data, list):
        return [nested_expand_missing(d, context, template, inherited_vars, env, path + (i,))
                for (i, d) in enumerate(data)]
    elif is_template(data):
        return render_variable(env, data, context)
    return data


def generate_layer(template: TemplateInfo, layer: dict, crispy_var: dict,
                   tmp_path: Path, repo_path: str, inherited_vars: dict = None,
                   verbose: bool = False):
    data = layer["cookiecutter"]
    context = {
        "cookiecutter": data,
        "crispycookie": crispy_var
    }
    env = StrictEnvironment(context=context)

    if verbose:
        print = _print
    else:
        print = no_print

    # Default any variables defined in cookiecutter.json but missing from .crispycookie.json
    defaulted_at_runtime = []
    for (key, value) in template.default_context.items():
        if key not in data:
            if inherited_vars and \
                    key in template.inherits and \
                    key in inherited_vars:
                # Make a deepcopy here so that updates in a prior template can't change an
                # earlier layer's data after the fact.  Isn't mutable fun?!?
                value = deepcopy(inherited_vars[key])
                print(f"Inheriting '{key}' from prior layer.")
            elif is_template(value):
                expanded_value = render_variable(env, value, data)
                value = expanded_value
            elif key.startswith("_"):
                # Prevent reporting _extensions and so on...
                pass
            elif isinstance(value, list):
                # Pick default item in the array
                value = value[0]
                print(f"Missing config for '{key}', using default value of {value}")
            elif isinstance(value, dict):
                print(f"Missing config for '{key}', using nested expansion technique...")
                value = nested_expand_missing(value, data, template, inherited_vars, env, (key,))
            defaulted_at_runtime.append(key)
            data[key] = value

    # TODO:  Rewrite the dictionary to be in the same order as the cookiecutter.json, with any
    #        unknown elements being kept in their original order as well

    out_dir = tmp_path / "build" / f"layer-{layer['layer_name']}"
    out_dir.mkdir(parents=True)
    template_path = str(template.path)
    context["cookiecutter"]["_template"] = f"{repo_path}/{template.path.name}"
    context["crispycookie"]["layer_name"] = layer['layer_name']
    # Run cookiecutter in a temporary directory
    project_dir = generate_files(template_path, context, output_dir=str(out_dir))
    #out_projects = [i for i in out_dir.iterdir() if i.is_dir()]
    # if len(out_projects) > 1:
    #    raise ValueError("Template generated more than one output folder!")

    # Remove from context any variables that were added from cookiecutter.json that are also marked
    # as ephemeral.  Ephemeral variables stored in crispycookie.json (hopefully, on purpose) will be preserved.
    for key in defaulted_at_runtime:
        block = False
        if key in template.ephemeral:
            block = "it is ephemeral"
        elif key in template.inherits:
            block = "of inheritance"
        if block:
            print(f"Preventing explicit retention of {key} because {block}")
            data.pop(key)
        else:
            print(f"Retaining {key} because it was explicitly set")

    # Remove vars that we added
    context["cookiecutter"].pop("_template")

    # To address backwards compatibility with my templates
    if "_template_version" in context["cookiecutter"]:
        del context["cookiecutter"]["_template_version"]

    if inherited_vars is not None:
        inherited_vars.update(dict_without_keys(data, *DO_NOT_INHERIT))

    return Path(project_dir)


def do_build(template_collection: TemplateCollection, args):
    verbose = args.verbose
    output = Path(args.output)
    output_folder = None
    if not output.is_dir():
        print(f"Missing output directory {output}", file=sys.stderr)
        return 1
    if args.config:
        print(f"Doing a fresh build.  Output will be written under {output}")
        config = json.load(args.config)
    else:
        config_file = output / ".crispycookie.json"
        if not config_file.is_file():
            print(f"Missing {config_file} file.  "
                  "Refusing to rebuild {output.name}", file=sys.stderr)
            return 1
        print(f"Regenerating a project {output.name} from existing {config_file.name}")
        # This seems silly, but to keep with the existing convention
        output_folder = output
        with open(config_file) as f:
            config = json.load(f)

    layers = config["layers"]
    inheritance_store = {}

    if "layer_mounts" in config:
        mount_points = config["layer_mounts"]
    else:
        print("No layers have been defined.  To enable this, add "
              "'layer_mounts' to the configuration file.")
        mount_points = []

    # These are available as {{ crispycookie.layer_mounts }};
    # For backwards compatibility with purse cookiecutter, use:
    #   {{ crispycookie.layer_mounts | default([]) }}
    crispycookie_var = {
        "layer_mounts": mount_points,
    }

    with TemporaryDirectory() as tmp_dir:
        tmpdir_path = Path(tmp_dir)
        layer_dirs = []
        for layer in layers:
            print(f"EXECUTING cookiecutter {layer['name']} template for layer {layer['layer_name']}")
            template = template_collection.get_template(layer["name"])
            layer_dir = generate_layer(template, layer, crispycookie_var, tmpdir_path, args.repo,
                                       inherited_vars=inheritance_store, verbose=verbose)
            layer_dirs.append(layer_dir)
            print("")

        top_level_names = set(ld.name for ld in layer_dirs)
        if len(top_level_names) > 1:
            raise ValueError(f"Found inconsistent top-level names of generated folders... {top_level_names}")
        top_level = top_level_names.pop()

        stage_folder = tmpdir_path / top_level

        if output_folder is None:
            output_folder = output / top_level

        if output_folder.is_dir():
            if args.overwrite:
                folder_name = output_folder.absolute().name if output_folder.name == "" else output_folder
                sys.stderr.write(f"Overwriting output directory {folder_name}, as requested.\n")
            else:
                sys.stderr.write(" *******************  ABORT  *******************\n\n")
                sys.stderr.write(f"Output directory {output_folder.absolute()} already exists.  "
                                 "Refusing to overwrite.\n")
                sys.stderr.write("\n")
                sys.exit(1)

        if mount_points:
            print(f"Applying project mount points:  {mount_points}")
            for i, layer_dir in enumerate(layer_dirs):
                layer_info = layers[i]
                layer_name = layer_info["layer_name"]
                move_to_layers(layer_dir, layer_name, mount_points)

        print("Combining cookiecutter layers")
        # Combine all cookiecutter outputs into a single location
        # XXX: Eventually make this a file system move (rename) opteration; faster than copying all the files
        for i, layer_dir in enumerate(layer_dirs):
            layer_info = layers[i]
            layer_name = layer_info["layer_name"]
            _copy_tree(layer_dir, stage_folder, layer_info=layer_name)

        print(f"Copying generated files to {output_folder}")
        _copy_tree(stage_folder, output_folder)

    for layer in layers:
        for clean_var in ["_extensions"]:
            if clean_var in layer["cookiecutter"]:
                del layer["cookiecutter"][clean_var]

    config["source"] = {
        "repo": args.repo,
        "rev": args.checkout,
    }
    config["tool_info"] = {
        "program": "CrispyCookie",
        "version": __version__,
    }
    with open(output_folder / ".crispycookie.json", "w") as fp:
        json.dump(config, fp, indent=4)


def _copy_tree(src: Path, dest: Path, layer_info=None):
    if not dest.is_dir():
        dest.mkdir()
    for p in src.iterdir():
        d = dest / p.name
        if p.is_file():
            if d.is_file() and layer_info:
                print(f"Layer {layer_info} has overwritten {d}")
            p.replace(d)
        elif p.is_dir():
            _copy_tree(p, d, layer_info)
        else:
            raise ValueError(f"Unsupported file type {p}")


def main():
    def add_repo_args(parser):
        parser.add_argument("repo", help="Path to local or remote repository "
                            "containing templates")
        parser.add_argument("-c", "--checkout", help="Branch, tag, or commit "
                            "to checkout from git repository.")
    parser = ArgumentParser()
    parser.set_defaults(function=None)
    parser.add_argument('--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))

    subparsers = parser.add_subparsers()

    config_parser = subparsers.add_parser(
        "config",
        description="Make a fresh configuration based on named template layers")
    config_parser.set_defaults(function=do_config)
    add_repo_args(config_parser)
    config_parser.add_argument("templates",
                               nargs="+",
                               metavar="TEMPLATE",
                               help="Template configurations to include in the "
                               "generated template.  Templates will be generated "
                               "in the order given.  The same template can be "
                               "provided multiple times, if desired.")
    config_parser.add_argument("-o", "--output", type=FileType("w"),
                               default=sys.stdout)

    list_parser = subparsers.add_parser("list",
                                        description="List available template layers")
    list_parser.set_defaults(function=do_list)
    add_repo_args(list_parser)

    build_parser = subparsers.add_parser("build",
                                         description="Build from a config file")
    build_parser.set_defaults(function=do_build)
    add_repo_args(build_parser)
    build_parser.add_argument("--config", type=FileType("r"),
                              help="JSON config file.  Needed the first time "
                              "a project is built.")
    build_parser.add_argument("-o", "--output",
                              default=".", metavar="DIR",
                              help="Top-level output directory.  Or the project "
                              "folder whenever doing a rebuild.")
    build_parser.add_argument("--overwrite", action="store_true", default=False)
    build_parser.add_argument("--verbose", action="store_true", default=False,
                              help="More output for var handling and such")

    args = parser.parse_args()
    if args.function is None:
        sys.stderr.write(parser.format_usage())
        sys.exit(1)

    abbreviations = {}

    local_clone_dir = "~/.crispy_cookie/repos"

    # Try local directory first.  (is_dir() may fail with git url)
    template_dir = None
    try:
        if Path(args.repo).expanduser().is_dir():
            template_dir = args.repo
    except OSError:
        pass

    if not template_dir:
        # Assume remote repository
        template_dir = clone(args.repo, args.checkout, local_clone_dir, True)

    tc = TemplateCollection(Path(template_dir))
    return args.function(tc, args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
