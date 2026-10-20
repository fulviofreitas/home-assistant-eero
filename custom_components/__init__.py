"""Make ``custom_components`` a regular package.

This file is not part of the integration and is not shipped: the release
zip is built from inside ``custom_components/eero``, Home Assistant's
hassfest skips files in this directory, and HACS only looks at its
sub-directories.

It exists for the analysers. The integration's domain, ``eero``, is also
the import name of the ``eero-api`` SDK it wraps. Without this file the
tools treat ``custom_components/eero`` as a top-level package called
``eero`` and resolve ``from eero.exceptions import ...`` to the
integration itself. With it they name the integration
``custom_components.eero`` and ``eero`` resolves to the SDK.
"""
