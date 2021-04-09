#!/usr/bin/env python3
"""Console script for crispy_cookie."""

import sys
from .core import TemplateError, TemplateCollection
from argparse import ArgumentParser, FileType
from pathlib import Path
import json
from cookiecutter.prompt import prompt_for_config
from collections import Counter


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


    args = parser.parse_args()
    if args.function is None:
        sys.stderr.write(parser.format_usage())
        sys.exit(1)

    tc = TemplateCollection(Path(args.root))
    return args.function(tc, args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
