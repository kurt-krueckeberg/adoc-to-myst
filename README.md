# AsciiDoc to MyST Markdown Converter

The bash script `adoc2myst` converts AsciiDoc files to MyST markdown. It
needs some basic setup firt, though.

## Basic Setup

Afte cloing the repo:

```bash
git clone https://github.com/kurt-krueckeberg/adoc-to-myst.git
```

These prerequistes must be done:

- AsciiDoctor must be installed. To install asciidoctor, wee how to [Install AsciiDoctor](https://docs.asciidoctor.org/asciidoctor/latest/install/).
- The [dbcookbook repo](https://github.com/tomschr/dbcookbook).

The `dbcookbook` repo must be cloned inside the **adoc-to-myst** folder.
Next, the **copy.xsl** file located in `dbcookbook/en/xml/structure/common`, must be copied to
`dbcookbook/en/xml/structure/db5-to-db4`.

## Create Symlink

One the basic setup is complete for the ~/ad
