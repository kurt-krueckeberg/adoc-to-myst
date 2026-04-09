# AsciiDoc to MyST Markdown Converter

The bash script `adoc2myst` converts AsciiDoc files to MyST markdown. It
needs some basic setup firt, though.

## Basic Setup

Afte cloing the repo:

```bash
git clone https://github.com/kurt-krueckeberg/adoc-to-myst.git
```

These prerequistes must be done:

1. AsciiDoctor must be installed. To install asciidoctor, wee how to [Install AsciiDoctor](https://docs.asciidoctor.org/asciidoctor/latest/install/).
2. The [dbcookbook repo](https://github.com/tomschr/dbcookbook) must be
  cloned witin **~/adoc-2-myst**:

```bash
cd ~/adoc-2-myst
git clone git@github.com:tomschr/dbcookbook.git
```

Next, the **copy.xsl** file located in `dbcookbook/en/xml/structure/common`, must be copied to
`dbcookbook/en/xml/structure/db5-to-db4`.

Next ,create `.gitignore` in `~/adoc-2-myst` and added:

```bash
/dbcookbook/
```
## Create Symlink in /usr/local/bin

sudo ln -s ~/adoc-2-myst/adco2myst /usr/local/bin/adoc2myst

sudo chmod +x /usr/local/bin/adoc2myst
