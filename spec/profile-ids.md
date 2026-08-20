# The register of profile ids

A container's header pins `profile_id`, and a device refuses a container
whose id does not match the profile it carries (§2.4). The number is an
identity in the sense a magic number is: nothing derives it, nothing
checks it, and two profiles that choose the same one produce containers
a reader cannot tell apart.

This page is what narrows that. It is a register, not a permission — a
profile may use any id it likes — and what it buys is that a published
number can be looked up before it is reused.

## The ranges

| Range | |
|---|---|
| `0` | Not available. It is what a compilation against no profile pins (§7.2.1) |
| `1` – `999` | Published profiles, recorded below |
| `1000` – `0x7FFFFFFF` | Unassigned. Ask here before taking one |
| `0x80000000` – `0xFFFFFFFF` | **Never allocated.** Private to one house, one vendor or one experiment; nothing published will ever be there to collide with |

The private range is the load-bearing half. A profile that will never
leave the building it was written for has no reason to coordinate with
anybody, and taking its number from above the boundary means it never
has to.

## Published profiles

| Id | Profile | |
|---|---|---|
| 1 | `home` | Home automation — [mcu-script/profile-home](https://github.com/mcu-script/profile-home) |

Adding a row is a pull request against this file. What is asked for is a
name, a link to where the profile lives, and nothing else: this project
does not review a profile's contents, and a register that implied it did
would be making a promise it cannot keep.
