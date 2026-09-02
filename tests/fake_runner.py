"""A stand-in test runner that honours --junit-xml.

Lets the integration tests exercise the real execution and report-parsing path
without requiring a third-party runner to be installed. It writes the same
xunit2 structure a runner produces.
"""

import argparse
import sys


TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="fake" tests="{total}" failures="{failures}" skipped="{skipped}">
{cases}</testsuite></testsuites>
"""


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit-xml", dest="junit_xml")
    parser.add_argument("-o", dest="overrides", action="append", default=[])
    parser.add_argument("--pass", dest="passing", type=int, default=2)
    parser.add_argument("--fail", dest="failing", type=int, default=2)
    parser.add_argument("--skip", dest="skipped", type=int, default=0)
    parser.add_argument("-q", action="store_true")
    args = parser.parse_args(argv)

    cases = []
    for index in range(args.passing):
        cases.append('<testcase classname="tests.test_sample" name="test_ok_%d"/>'
                     % index)
    for index in range(args.failing):
        cases.append(
            '<testcase classname="tests.test_sample" name="test_broken_%d">'
            '<failure message="assert failed">boom</failure></testcase>' % index
        )
    for index in range(args.skipped):
        cases.append(
            '<testcase classname="tests.test_sample" name="test_skipped_%d">'
            '<skipped message="skipped"/></testcase>' % index
        )

    if args.junit_xml:
        with open(args.junit_xml, "w", encoding="utf-8") as handle:
            handle.write(
                TEMPLATE.format(
                    total=args.passing + args.failing + args.skipped,
                    failures=args.failing,
                    skipped=args.skipped,
                    cases="\n".join(cases),
                )
            )

    total = args.passing + args.failing + args.skipped
    print("%d passed, %d failed, %d skipped in 0.10s"
          % (args.passing, args.failing, args.skipped))
    print("collected %d items" % total)
    return 1 if args.failing else 0


if __name__ == "__main__":
    sys.exit(main())
