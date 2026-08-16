# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0

add_executable(test_header test_header.c)
target_link_libraries(test_header PRIVATE mcuscript)
add_test(NAME header COMMAND test_header)

# The reference embedder the Python test suite drives. Not a test in
# itself: it is how the runtime becomes observable from outside, and the
# C backend will be driven through the same output protocol.
add_executable(mcuscript-run mcuscript_run.c)
target_link_libraries(mcuscript-run PRIVATE mcuscript)
