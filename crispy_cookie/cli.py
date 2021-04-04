#!/usr/bin/env python3
"""Console script for crispy_cookie."""

import sys
from .core import TemplateError, TemplateCollection
from argparse import ArgumentParser, FileType
from pathlib import Path
from cookiecutter.prompt import prompt_for_config
from collections import Counter


def do_config(template_collection: TemplateCollection, args):
    layer_count = Counter()
    doc = {}
    layers = doc["layers"] = []
    print(f"Expanding templates named:  {args.templates}")
    for template_name in args.templates:
        tmp = template_collection.get_template(template_name)
        layer_count[tmp.name] += 1
        n = layer_count[tmp.name]
        context = dict(tmp.default_context)
        context["layer"] = f"00-{tmp.name}{n}"
        print(f"{template_name} {n}:  layer_name={context['layer']}"
              f"  Context:  {context}")
        layer = {
            "name": tmp.name,
            "params": context,
        }

        cc_context = {"cookiecutter": context}
        final = prompt_for_config(cc_context)

        layer["prompt_output"] = final
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

    args = parser.parse_args()
    if args.function is None:
        sys.stderr.write(parser.format_usage())
        sys.exit(1)

    tc = TemplateCollection(Path(args.root))
    return args.function(tc, args)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
