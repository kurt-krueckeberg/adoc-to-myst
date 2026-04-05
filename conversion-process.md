# Conversion Route
.adoc
  ↓
Asciidoctor → DocBook 5
  ↓
strip namespace + XSLT → DocBook 4
  ↓
Python script → MyST Markdown

## Setting up the XSLT Step

This step down-converts DocBook 5 to DocBook 4. It uses a github repo.

1. git clone https://github.com/tomschr/dbcookbook.git && cd dbcookbook

2. cp dbcookbook/en/xml/structure/common/copy.xsl \                                                                                              sphinx-nla
   dbcookbook/en/xml/structure/db5-to-db4/
 
## Pipeline Steps

1. AsciiDoc → DocBook 5

asciidoctor -b docbook input.adoc -o doc5.xml

2. Strip namespace from DocBook 5 file

sed 's/xmlns="http:\/\/docbook.org\/ns\/docbook"//' doc5.xml > doc5-nons.xml

3. DocBook 5 → DocBook 4

xsltproc \
  --path $HOME/temp/dbcookbook/en/xml/structure/db5-to-db4 \
  $HOME/temp/dbcookbook/en/xml/structure/db5-to-db4/db5to4.xsl \
  doc5-nons.xml > doc4.xml

4. DocBook 4 → MyST

python3 convert.py doc4.xml > output.md

## How to Go About Further Testing convert.py

Test systematically by...

### Pick 2–3 representative documents:

1. **Simple file**

   * basic paragraphs
   * 1 simple table (no spans)
   * ordered list
   * unordered list

2. **Moderate file**

   - multiple tables
     - tables with frame=... and grid=...
   - xrefs inside tables
   - images

3. **Complex file**

   - spanning tables
   - nested sections
   - mixed content

---

### What to evaluate (strictly)

For each file, check only:

#### 1. Tables

* simple → `list-table`
* spans → `flat-table`
* no missing rows or cells

---

#### 2. Links

- internal links → `.md` ✔
- xrefs → `{ref}` ✔

---

#### 3. Structure

- headings correct level
- no missing sections

---

#### 4. Images

- correct path
- captions preserved

---

### What NOT to do

* Don’t generalize early
* Don’t refactor the script broadly
* Don’t “improve” working parts

---

### How to handle issues

When something fails:

> isolate → fix → re-run

Example:

* one table breaks → adjust `convert_table()`
* one inline case fails → adjust `render_inline()`

Each fix should be **local and surgical**

---

## Optional (but very useful)

You may want to wrap your pipeline into a single command:

```bash
asciidoctor -b docbook input.adoc -o doc5.xml
sed 's/xmlns="http:\/\/docbook.org\/ns\/docbook"//' doc5.xml > doc5-ns.xml
xsltproc db5to4.xsl doc5-ns.xml > doc4.xml
python3 convert.py doc4.xml > output.md
```

This removes friction and lets you iterate quickly.

---

### Bottom line

> You are no longer searching for a solution—you are now **validating and stabilizing one**.

That’s a fundamentally different phase, and much easier to complete.

---

When you test the next files, bring one failure at a time if needed. Each one will be small and fixable.

