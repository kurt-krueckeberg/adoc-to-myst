# AsciiDoc to MyST Markdown Converter

The bash script adoc-to-myst.sh converts an AsciiDoc file to MyST markdown.
It relies on these prerequistes:

- AsciiDoctor must be installed. See how to [Install
  AsciiDoctor](https://docs.asciidoctor.org/asciidoctor/latest/install/).
- [dbcookbook repo](https://github.com/tomschr/dbcookbook).


The dbcookbook must be cloned inside the directory for *adoc-to-myst*.

Also the **copy.xsl** file, which is located in dbcookbook/en/xml/structure/common, must be copied to
**dbcookbook/en/xml/structure/db5-to-db4**.
