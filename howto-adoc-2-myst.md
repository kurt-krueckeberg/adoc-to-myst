# Usage Instructions for adoc-2-my.sh

Here are the **concise usage instructions**:

---

## 1. Setting `DBCOOKBOOK_DIR` (location of dbcookbook)

Default (if not set):

```bash
$HOME/temp/dbcookbook
```

If you move it, set the variable before running the script:

```bash
export DBCOOKBOOK_DIR=/path/to/dbcookbook
./adoc-2-myst.sh input.adoc
```

Or inline (one-off):

```bash
DBCOOKBOOK_DIR=/path/to/dbcookbook ./adoc-2-myst.sh input.adoc
```

---

## 2. Using the `-o` output parameter

Specify output file and/or location:

```bash
./adoc-2-myst.sh input.adoc -o output.md
```

or:

```bash
./adoc-2-myst.sh -o /tmp/output.md input.adoc
```

---

## 3. Default behavior (no `-o`)

If you omit `-o`, output is:

```bash
<same directory>/<same basename>.md
```

Example:

```bash
./adoc-2-myst.sh sample.adoc
# → sample.md
```

---

## TL;DR

* `DBCOOKBOOK_DIR` → controls where XSL files live
* `-o` → controls output filename/location
* Both are optional and override defaults only when needed

