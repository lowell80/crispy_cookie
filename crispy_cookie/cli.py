#!/usr/bin/env python3
"""Console script for crispy_cookie."""

import sys
from .core import TemplateError, TemplateInfo, TemplateCollection
from argparse import ArgumentParser, FileType
from pathlib import Path
import json
import shutil
from cookiecutter.prompt import prompt_for_config
from cookiecutter.generate import generate_files
from collections import Counter
from tempfile import TemporaryDirectory


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


def generate_layer(template : TemplateInfo, layer: dict, tmp_path: Path):
    context = { "cookiecutter": layer["cookiecutter"] }
    out_dir = tmp_path / "build" / f"layer-{layer['name']}"
    out_dir.mkdir(parents=True)
    template_path = str(template.path)
    context["cookiecutter"]["_template"] = template_path
    # Run cookiecutter in a temporary directory
    project_dir = generate_files(template_path, context, output_dir=str(out_dir))
    #out_projects = [i for i in out_dir.iterdir() if i.is_dir()]
    #if len(out_projects) > 1:
    #    raise ValueError("Template generated more than one output folder!")
    return Path(project_dir)


def do_build(template_collection: TemplateCollection, args):
    config = json.load(args.config)
    layers = config["layers"]

    with TemporaryDirectory() as tmp_dir:
        tmpdir_path = Path(tmp_dir)
        layer_dirs = []
        for layer in layers:
            print(f"EXECUTING cookiecutter {layer['name']} template for layer {layer['layer_name']}")
            template = template_collection.get_template(layer["name"])
            layer_dir = generate_layer(template, layer, tmpdir_path)
            layer_dirs.append(layer_dir)

        top_level_names = [ld.name for ld in layer_dirs]
        if len(set(top_level_names)) > 1:
            raise ValueError(f"Found inconsistent top-level names of generated folders... {top_level_names}")
        top_level = top_level_names[0]

        stage_folder = tmpdir_path / top_level
        output_folder = Path(args.output) / top_level

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


def _copy_tree(src: Path, dest: Path, layer_info=None):
    if not dest.is_dir():
        if dest.exists():
            raise ValueError(f"{dest} exists, but is not a directory")
        else:
            dest.mkdir()
    for p in src.iterdir():
        d = dest / p.name
        if p.is_file():
            if d.is_file():
                if layer_info:
                    print(f"Layer {layer_info} has overwritten {d}")
            shutil.copy2(p, d)
        elif p.is_dir():
            _copy_tree(p, d, layer_info)
        else:
            raise ValueError(f"Unsupported file type {p}")




def main():
    parser = ArgumentParser()
    parser.set_defaults(function=None)
    parser.add_argument("--root", default=".")
    subparsers = parser.add_subparsers()

    config_parser = subparsers.add_parser(
        "config",
        description="Make a fresh configuration based on named template layers")
    config_parser.set_defaults(function=do_config)
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

    build_parser = subparsers.add_parser("build",
                                         description="Build from a config file")
    build_parser.set_defaults(function=do_build)
    build_parser.add_argument("config", type=FileType("r"),
                              help="JSON config file")
    build_parser.add_argument("-o", "--output",
                              default=".", metavar="DIR",
                              help="Output directory")
    build_parser.add_argument("--overwrite", action="store_true", default=False)



    args = parser.parse_args()
    if args.function is None:
        sys.stderr.write(parser.format_usage())
        sys.exit(1)

    tc = TemplateCollection(Path(args.root))
    return args.function(tc, args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
