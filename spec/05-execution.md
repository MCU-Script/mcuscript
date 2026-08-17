<!--
SPDX-FileCopyrightText: 2026 The MCUScript Contributors
SPDX-License-Identifier: Apache-2.0
-->

# 5. Execution

## 5.1 The model

A script does not run; it is **invoked**. The embedder decides when —
a sensor reported, a timer elapsed, a command arrived — and calls one
entry point by name. The entry point runs **to completion** and
returns, possibly with a value.

Three properties follow, and the rest of this chapter depends on them:

- **No re-entrancy.** An entry point is never invoked while any entry
  point of the same program is running. An embedder that receives a
  trigger during a run queues or drops it; it does not nest.
- **No concurrency inside a program.** There is no thread, no
  coroutine, no yield.
- **Run to completion.** A script does not wait for anything. There is
  no sleep, no I/O that blocks, no `await`. A host function that would
  need to wait is the embedder's problem to solve outside the script.

This is not a simplification to be relaxed later. It is what allows a
device to hold **one** operand stack sized to its worst script (§1.2),
what makes the static resource computation meaningful, and what keeps a
script off the critical path of a radio stack that has its own timing
to keep.

## 5.2 State

Between invocations, a program has none. Locals do not persist; there
is no global storage; the operand stack is empty at entry and empty at
exit. Everything that outlives an invocation lives in the host, as an
entity.

That is a real constraint and worth stating rather than discovering: a
filter that needs the previous reading to compute a moving average
cannot keep it in a local. It reads it from an entity the host owns
and writes it back. The host is the memory, deliberately — it already
manages persistence, it knows what survives a reboot, and a script that
cannot hold state cannot leak it either.

## 5.3 Frames

A frame is: the callee's locals, then its operand stack. Arguments
pushed by the caller become the first locals (§3.6); remaining locals
begin `unavailable`.

That sentence is meant literally, and it is what makes a call cheap. The
arguments are already on the caller's stack, in order, at the top —
which is exactly where the callee's locals have to be. So a frame
**overlaps its caller's by `param_count` slots** and nothing is copied:
the callee's frame begins `param_count` slots below the caller's stack
pointer, and returning restores the pointer to that same place, which
removes the arguments as a side effect of leaving.

Because the value stack and the locals are all slots (§1.2), a frame is
`(local_count + max_stack)` slots, and the requirement for an
invocation is that summed along the deepest call chain — the overlap
above makes the sum an over-estimate, which is the right direction for a
number a device sizes a buffer from. It follows from the container, so
the VM allocates once and never checks a bound at runtime. There is no
stack growth, no guard page, no overflow test in the interpreter loop.

`max_call_depth` in the record (§4.3) counts *frames*, not slots, which
is why it is not the number anything is allocated from: frames are not a
resource, slots are. It is there to be checked against — a verifier
recomputes it, and a container where the file and its code disagree is
non-conforming.

`RET_V` pops the return value, discards the frame, and pushes the value
into the caller's stack. `RET` discards the frame. In a conforming
container neither can leave the caller's stack in an unexpected shape,
since §2.6 point 3 fixes the shape at every call site.

## 5.4 Recursion and its cap

Recursion is permitted. Unbounded recursion is not, and the difference
is a **declared cap**.

The language has a default depth, and a function may override it at its
own declaration — where the cost is incurred and where a reader will
look for it. The cap applies to a **cycle in the call graph, not to a
function**: the compiler finds the strongly connected components of the
graph and each one carries a cap, because `a → b → a` consumes the
stack exactly as `a → a` does and a self-call-only rule would let the
harder-to-notice case through.

**A cap is a number of frames, not of round trips.** With a cap of 5,
`a → a → a → a → a` is the limit and so is `a → b → a → b → a`: five
activations of that component's members, however they are spelled. This
follows from the counter below rather than being an extra rule, and it
is the only reading both backends can implement without knowing the
cycle's shape.

A cycle without a cap makes a container non-conforming
(`uncapped_recursion`), and the worst case is the cap times the largest
frame in the cycle — which is what makes §5.3's single allocation
possible.

**Both backends enforce it the same way, at runtime.** A cap is a
static bound on the *worst case*, but whether a particular run recurses
that deep is data. So each cycle carries a counter, incremented on
entry to any of its members and decremented on return; exceeding the
cap is a fault (§5.5). Being invoked counts as an entry, so an entry
point inside a cycle occupies the first of its cap.

In the VM the counter lives beside the frame machinery, so it is per
invocation and unwinding a fault cannot leave it wrong. In generated C
— where MCUScript functions become ordinary C functions on the
embedder's thread stack, and the VM's frame apparatus does not exist —
it is a static counter with the same increment, decrement and test, and
the decrement is on **every** path out of the function including the one
a fault takes. A counter that leaked on the error path would refuse the
next invocation for something the previous one did. The C compiler will
often prove the whole thing away.

This is the answer to the question the C backend otherwise leaves open:
C has no recursion counter, so the transpiler emits one. Without it the
transpiled program would recurse until the thread stack ran out, which
on a device with no MMU is not a crash but silent corruption — and it
would behave differently from the VM, which is the one thing this
project does not permit.

## 5.5 Faults

A fault ends the invocation. There are three, and there are deliberately
no others:

| Fault | Cause |
|---|---|
| `absent_condition` | a conditional branch reached a `bool` that is not `valid` (§1.3.1) |
| `recursion_limit` | a cycle's counter exceeded its cap (§5.4) |
| `host_fault` | a host function signalled failure |

Everything else that could have been a fault is a value instead.
Division by zero yields `invalid`; an out-of-range float conversion
yields `invalid`; an absent sensor yields `unavailable`. This is the
consistent choice, and the reason is that a value can be handled by the
script that has the context to handle it, while a fault can only be
reported to a user who does not.

There is no fault for a bad opcode, a stack overflow, a bad index or a
type error, because a conforming container cannot produce one (§2.6).
An implementation is not required to detect these; a container that
contains one is outside what this specification defines, and inventing a
fault for it would only make the undefined look handled.

A fault is reported to the embedder with its kind, the entry point, and
— if the container carried a `dbug` section — the source position. What
the embedder then does is its own: log it, fall back to a previous
script, disable the script, or all three. The specification requires
only that a fault be reported and that the invocation stop.

## 5.6 Termination

Every invocation terminates. This is proved at load, not enforced at
runtime:

- the control flow graph of each function is acyclic, because backward
  jumps are rejected (§3.8);
- the call graph's cycles all carry a finite cap (§5.4).

Together those bound the number of instructions an invocation can
execute by a number that follows from the container. So there is no
instruction budget, no counter in the dispatch loop, and no per-opcode
cost — which matters twice over: the interpreter's inner loop stays
small, and the C backend has nothing artificial to reproduce. An instruction counter is natural in a
VM and absurd in compiled C, and requiring one would have put the two
backends at odds over their own arithmetic.

When counted loops arrive (§3.8) the proof extends to them by their
bound, and the property is meant to survive: a construct that could
make termination undecidable does not belong in this language.

## 5.7 Writes and when they land

A script observes its own writes: read back an entity it wrote and it
reads what it wrote (§1.6).

When those writes become visible *outside* the invocation is the
embedder's policy and this specification does not constrain it. An
embedder may apply each write as it happens, or buffer them all and
commit when the invocation returns. The second is worth recommending —
it is the industrial arrangement, and it means an invocation that
faults halfway leaves the device unchanged rather than half-updated —
but it is a recommendation, because the tradeoff belongs to whoever
owns the device.

An embedder that buffers satisfies §1.6 by consulting its own buffer on
reads, which costs it nothing it was not already doing.

**Both backends must get the same policy.** The VM and the transpiled C
reach the host through the same interface, so this is automatic unless
an embedder goes out of its way to implement the interface twice.

## 5.8 What an implementation must not do

Collected here because each one would silently break a promise made
elsewhere:

- **Do not accept a container whose header says it needs something this
  build does not have** (§2.5). That is an identity check, it is cheap,
  and skipping it means decoding an instruction that is not implemented.
- **Do not present a runtime as safe against non-conforming input**
  unless it verifies (§2.6). A runtime alone establishes that a
  container is *meant* for it, never that it is sound; an embedder whose
  delivery path is untrusted needs a verifier or an authenticated path,
  and the language cannot supply either.
- **Do not fault where the specification names a value.** Turning a
  division by zero into a fault would make a script that handles
  `invalid` correctly die anyway.
- **Do not take a branch on a non-valid condition.** Choosing the false
  branch when a sensor has not reported is how an absent reading
  becomes a wrong action.
- **Do not let a value's validity state be lost across a host call.**
  The state is part of the value, and an embedder that drops it cannot
  distinguish "the script computed zero" from "the script knew
  nothing".
- **Do not add a numeric behaviour C leaves open.** §1.5 pins every
  case, and an implementation that follows its compiler instead of the
  specification will diverge from the other backend on exactly the
  inputs nobody tested.
