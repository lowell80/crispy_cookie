#!/usr/bin/env python3
"""Console script for crispy_cookie."""

import json
import sys
from argparse import ArgumentParser, FileType
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from cookiecutter.environment import StrictEnvironment
from cookiecutter.generate import generate_files
from cookiecutter.prompt import prompt_for_config, render_variable
# from cookiecutter.repository import determine_repo_dir
from cookiecutter.vcs import clone

from . import __version__
from .core import TemplateCollection, TemplateError, TemplateInfo

# XXX:  Could use cookiecutter.repository.determine_repo_dir to fetch remote git


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

    for template_name in templates:
        tmp = template_collection.get_template(template_name)
        layer_count[tmp.name] += 1
        n = layer_count[tmp.name]
        context = dict(tmp.default_context)
        layer_name = tmp.default_layer_name
        if n > 1:
            layer_name += f"-{n}"

        '''
        # Prompt user
        layer_name_prompt = input(f"Layer name?  [{layer_name}] ")
        if layer_name_prompt:
            layer_name = layer_name_prompt
        '''
        context["layer"] = layer_name
        print(f"{template_name} {n}:  layer={layer_name}"
              #      f"  Context:  {context}"
              )
        layer = {
            "name": tmp.name,
            "layer_name": layer_name,
            "cookiecutter": context,
        }

        cc_context = {"cookiecutter": context}

        # Apply inherited variables
        for var in tmp.inherits:
            if var in shared_args:
                cc_context["cookiecutter"][var] = shared_args[var]

        # Prompt the user
        final = prompt_for_config(cc_context)

        layer["cookiecutter"] = final
        layer["layer_name"] = final["layer"]

        # Update shared args for next layer to inherit from
        final2 = dict(final)
        for var_name in ["layer", "_extensions"]:
            if var_name in final2:
                final2.pop(var_name)
        shared_args.update(final2)

        layers.append(layer)
    json.dump(doc, args.output, indent=4)


def generate_layer(template: TemplateInfo, layer: dict, tmp_path: Path, repo_path: str):
    data = layer["cookiecutter"]
    context = {"cookiecutter": data}
    env = StrictEnvironment(context=context)

    for (key, value) in template.default_context.items():
        if key not in data:
            if "{{" in value:
                expanded_value = render_variable(env, value, data)
                ## expanded_value = env.from_string(value).render(data)
                print(f"Missing config for '{key}', using default value of {expanded_value} rendered from {value}")
                value = expanded_value
            else:
                print(f"Missing config for '{key}', using default value of {value}")
            data[key] = value

    out_dir = tmp_path / "build" / f"layer-{layer['name']}"
    out_dir.mkdir(parents=True)
    template_path = str(template.path)
    context["cookiecutter"]["_template"] = f"{repo_path}/{template.path.name}"
    # Run cookiecutter in a temporary directory
    project_dir = generate_files(template_path, context, output_dir=str(out_dir))
    #out_projects = [i for i in out_dir.iterdir() if i.is_dir()]
    # if len(out_projects) > 1:
    #    raise ValueError("Template generated more than one output folder!")
    return Path(project_dir)


def do_build(template_collection: TemplateCollection, args):
    output = Path(args.output)
    if args.config:
        print(f"Doing a fresh build.  Output will be written under {output}")
        config = json.load(args.config)
    else:
        config_file = output / ".crispycookie.json"
        if not config_file.is_file():
            print(f"Missing {config} file.  Refusing to rebuild {output.name}", file=sys.stderr)
            return 1
        print(f"Regenerating a project {output.name} from existing {config_file.name}")
        # This seems silly, but to keep with the existing convention
        output = output.parent
        with open(config_file) as f:
            config = json.load(f)

    layers = config["layers"]

    with TemporaryDirectory() as tmp_dir:
        tmpdir_path = Path(tmp_dir)
        layer_dirs = []
        for layer in layers:
            print(f"EXECUTING cookiecutter {layer['name']} template for layer {layer['layer_name']}")
            template = template_collection.get_template(layer["name"])
            layer_dir = generate_layer(template, layer, tmpdir_path, args.repo)
            layer_dirs.append(layer_dir)
            print("")

        top_level_names = [ld.name for ld in layer_dirs]
        if len(set(top_level_names)) > 1:
            raise ValueError(f"Found inconsistent top-level names of generated folders... {top_level_names}")
        top_level = top_level_names[0]

        stage_folder = tmpdir_path / top_level
        output_folder = output / top_level

        if output_folder.is_dir():
            if args.overwrite:
                sys.stderr.write(f"Overwriting output directory {output_folder}, as requested.\n")
            else:
                sys.stderr.write(f"Output directory {output_folder} already exists.  "
                                 "Refusing to overwrite.\n")
                sys.exit(1)

        print("Combining cookiecutter layers")
        # Combine all cookiecutter outputs into a single location
        # XXX: Eventually make this a file system move (rename) opteration; faster than copying all the files
        for i, layer_dir in enumerate(layer_dirs):
            layer_info = layers[i]
            layer_name = layer_info["name"]
            _copy_tree(layer_dir, stage_folder)

        print(f"Copying generated files to {output_folder}")
        _copy_tree(stage_folder, output_folder)

    for layer in layers:
        for clean_var in ["_extensions"]:
            if clean_var in layer["cookiecutter"]:
                del layer["cookiecutter"][clean_var]

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
            p.rename(d)
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

    args = parser.parse_args()
    if args.function is None:
        sys.stderr.write(parser.format_usage())
        sys.exit(1)

    abbreviations = {}
    local_clone_dir = "~/.crispy_cookie/repos"
    template_dir = clone(args.repo, args.checkout, local_clone_dir, True)

    tc = TemplateCollection(Path(template_dir))
    return args.function(tc, args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
