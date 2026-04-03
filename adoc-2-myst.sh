#!/usr/bin/env bash

set -euo pipefail

OUTPUT_OVERRIDE=""
DOC4_DIR_OVERRIDE=""
INPUT=""
DEBUG="${DEBUG:-0}"

# --- Parse args (order-independent) ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      OUTPUT_OVERRIDE="$2"
      shift 2
      ;;
    --doc4-dir)
      DOC4_DIR_OVERRIDE="$2"
      shift 2
      ;;
    -*)
      echo "Unknown option: $1"
      echo "Usage: $0 [-o output.md] [--doc4-dir /path/to/folder] <input.adoc>"
      exit 1
      ;;
    *)
      INPUT="$1"
      shift
      ;;
  esac
done

# --- Input validation ---
if [[ -z "$INPUT" ]]; then
  echo "Usage: $0 [-o output.md] [--doc4-dir /path/to/folder] <input.adoc>"
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "Error: file not found: $INPUT"
  exit 1
fi

# --- Derive names ---
BASENAME="$(basename "$INPUT" .adoc)"

# --- Temp working directory ---
TMPDIR="$(mktemp -d)"

if [[ "$DEBUG" -eq 1 ]]; then
  echo "DEBUG: using temp dir: $TMPDIR"
else
  trap 'rm -rf "$TMPDIR"' EXIT
fi

DOC5="$TMPDIR/doc5.xml"
DOC5_NONS="$TMPDIR/doc5-nons.xml"

# --- doc4 output handling ---
if [[ -n "$DOC4_DIR_OVERRIDE" ]]; then
  mkdir -p "$DOC4_DIR_OVERRIDE"
  DOC4="$DOC4_DIR_OVERRIDE/doc4.xml"
else
  DOC4="$TMPDIR/doc4.xml"
fi

# --- Output handling ---
if [[ -n "$OUTPUT_OVERRIDE" ]]; then
  OUTPUT_MD="$OUTPUT_OVERRIDE"
else
  OUTPUT_MD="$(dirname "$INPUT")/${BASENAME}.md"
fi

# --- Configure dbcookbook location ---
DBCOOKBOOK_DIR="${DBCOOKBOOK_DIR:-$HOME/temp/dbcookbook}"
XSL_DIR="$DBCOOKBOOK_DIR/en/xml/structure/db5-to-db4"
XSL_FILE="$XSL_DIR/db5to4.xsl"

if [[ ! -f "$XSL_FILE" ]]; then
  echo "Error: db5to4.xsl not found at: $XSL_FILE"
  echo "Set DBCOOKBOOK_DIR to the correct location."
  exit 1
fi

# --- Step 1 ---
asciidoctor -b docbook "$INPUT" -o "$DOC5"

# --- Step 2 ---
sed 's/xmlns="http:\/\/docbook.org\/ns\/docbook"//' "$DOC5" > "$DOC5_NONS"

# --- Step 3 ---
xsltproc \
  --path "$XSL_DIR" \
  "$XSL_FILE" \
  "$DOC5_NONS" > "$DOC4"

# --- Step 4 ---
python3 /home/kurt/sphinx-nla/convert.py "$DOC4" > "$OUTPUT_MD"

echo "Done: $OUTPUT_MD"
echo "DocBook 4 file: $DOC4"
