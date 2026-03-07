#!/bin/bash
# Build script for groc-IRC assembly routines
# Requires: nasm, gcc

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Building groc-IRC assembly library..."

# Assemble
nasm -f elf64 grocbot_asm.asm -o grocbot_asm.o
echo "  Assembled grocbot_asm.o"

# Link as shared library
gcc -shared -o grocbot_asm.so grocbot_asm.o -nostartfiles
echo "  Linked grocbot_asm.so"

# Cleanup object file
rm -f grocbot_asm.o
echo "  Cleaned up"

echo "Build complete: grocbot_asm.so"
echo "Copy to project root or set ASM_LIB_PATH environment variable"
