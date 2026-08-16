# SPDX-FileCopyrightText: 2026 The MCUScript Contributors
# SPDX-License-Identifier: Apache-2.0
#
# The runtime builds as a plain static library with no dependencies, and
# the four source files can equally be dropped into somebody else's
# build system — that is the point of having no dependencies. This file
# exists so the tests have something to run, not because CMake is part
# of the contract.

cmake_minimum_required(VERSION 3.20)
project(mcuscript_runtime C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(mcuscript STATIC src/load.c src/vm.c)
target_include_directories(mcuscript PUBLIC include PRIVATE src)

# Warnings are errors. A runtime that runs on a device with no MMU does
# not get to ignore a sign-conversion warning.
target_compile_options(
  mcuscript
  PRIVATE -Wall
          -Wextra
          -Werror
          -Wconversion
          -Wsign-conversion
          -Wshadow
          -Wstrict-prototypes
          -Wmissing-prototypes
          -Wcast-qual
          -Wpointer-arith)

include(CTest)
if(BUILD_TESTING)
  add_subdirectory(tests)
endif()
