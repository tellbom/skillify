# Local Document Search

The endpoint registers a selected directory under an alias. Search requests use only that
alias and return bounded filename/metadata/full-text matches; no vector index or whole-disk
scan is created. Sending matched content beyond the endpoint is a separate confirmed action.
