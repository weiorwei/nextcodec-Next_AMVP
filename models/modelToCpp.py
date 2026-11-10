#!/usr/bin/env python

import argparse

parser = argparse.ArgumentParser(
                  prog = "ModelToCpp",
                  description = "Dump a model description to a char[] variable in C++ syntax")

parser.add_argument( '-i', '--input', required=True )
parser.add_argument( '-o', '--output', required=True )
parser.add_argument( '-n', '--varname', default="defaultNnlfModel" )

args = parser.parse_args()

with open(args.output, "w") as output:
    output.write("\n\n");
    output.write("char {}[] = ".format(args.varname));
    with open(args.input, "rb") as input:
        while chunk := input.read(40):
            output.write("\n  \"");
            for c in chunk:
                output.write(f"\\x{c:02x}")
            output.write("\"")
        output.write(";\n")
    output.write("\n\n")
