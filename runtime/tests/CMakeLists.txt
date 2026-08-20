# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0

add_executable(test_header test_header.c)
target_link_libraries(test_header PRIVATE mcuscript)
add_test(NAME header COMMAND test_header)

add_executable(test_values test_values.c)
target_link_libraries(test_values PRIVATE mcuscript)
add_test(NAME values COMMAND test_values)

# The world a test describes in a file, and the output protocol both
# backends answer in. Linked into the VM runner here, and compiled
# alongside generated C by the differential harness.
add_library(hostfile STATIC hostfile.c)
target_link_libraries(hostfile PUBLIC mcuscript)
target_include_directories(hostfile PUBLIC .)

# The reference embedder the Python test suite drives.
add_executable(mcuscript-run mcuscript_run.c)
target_link_libraries(mcuscript-run PRIVATE mcuscript hostfile)
