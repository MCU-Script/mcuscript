# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
"""The MCUScript host toolchain.

Nothing here runs on a device. The toolchain reads and writes the
container format of the specification, checks it, and lowers it to C;
the VM that executes a container is the C runtime in ``runtime/``.
"""

from __future__ import annotations

__all__ = ["SPEC_VERSION", "__version__"]

__version__ = "0.1.0.dev0"

#: The specification version this toolchain implements. It is not the
#: package version and it is not the container format version — the
#: three are different things on purpose (spec/README.md).
SPEC_VERSION = "0.1.0-draft"
