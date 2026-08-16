# Security Policy

## Supported versions

MCUScript has no implementation and no releases. This policy takes full
effect with the first release; until then, reports about the repository
scaffold are still welcome.

## Reporting a vulnerability

**Do not open public issues for security vulnerabilities.**

Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** on this repository
([direct link](https://github.com/mcu-home/mcuscript/security/advisories/new)).

We aim to acknowledge reports within **3 business days**. Please include a
description of the issue, the affected component (compiler, bytecode
format, VM), and reproduction steps where possible.

## Scope

A scripting engine for microcontrollers has an unusually sharp security
boundary, and it is worth naming before there is any code to attack:

- **Bytecode is untrusted input.** The device receives compiled
  bytecode over a management channel, not source it compiled itself. A
  malformed or hostile bytecode image must never crash, hang or
  corrupt a node — the verifier is a security component, not a
  convenience.
- **Memory safety of the VM.** Out-of-bounds access, stack overflow,
  type confusion and integer overflow in the interpreter loop, on
  targets with no MMU and often no MPU configuration to fall back on.
- **Resource exhaustion.** A script that never yields, allocates
  without bound, or starves the network stack is a denial of service on
  a device that has no operator.
- **The compiler as a supply chain.** Host-side compilation means the
  toolchain decides what runs on every device that receives its output.
- **Escape from the script surface.** Scripts must reach only the API
  surface their embedder exposes — never arbitrary memory, never the
  device's credentials.

Anything that lets a script do something its embedder did not offer it
is a vulnerability, even if the script had to be authorized to run.
