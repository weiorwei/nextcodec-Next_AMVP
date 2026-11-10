NextSoftware2 used in JVET CfE
==============================

This software package has been used to generate the two Call for Evidence responses from Ericsson, Fraunhofer HHI and Nokia, described in [JVET-AN0267](https://jvet-experts.org/doc_end_user/current_document.php?id=16250).

The source code is stored in a Git repository. The most recent version can be retrieved using the following commands:

```bash
git clone https://vcgit.hhi.fraunhofer.de/jvet-ahg-ecbvc/JVET-AN0267.git
cd JVET-AN0267
```

Build instructions
==================

The CMake tool is used to create platform-specific build files. 

Although CMake may be able to generate 32-bit binaries, **it is generally suggested to build 64-bit binaries**. 32-bit binaries are not able to access more than 2GB of RAM, which will not be sufficient for coding larger image formats. Building in 32-bit environments is not tested and will not be supported.


Build instructions for plain CMake (suggested)
----------------------------------------------

**Note:** A working CMake installation is required for building the software.

CMake generates configuration files for the compiler environment/development environment on each platform. 
The following is a list of examples for Windows (MS Visual Studio), macOS (Xcode) and Linux (make).

Open a command prompt on your system and change into the root directory of this project.

Create a build directory in the root directory:
```bash
mkdir build 
```

Use one of the following CMake commands, based on your platform. Feel free to change the commands to satisfy
your needs.

**Windows Visual Studio 17/19/22 64 Bit:**

Use the proper generator string for generating Visual Studio files, e.g. for VS 2022:

```bash
cd build
cmake .. -G "Visual Studio 17 2022 Win64"
```

Then open the generated solution file in MS Visual Studio.

For VS 2017 use "Visual Studio 15 2017 Win64", for VS 2019 use "Visual Studio 16 2019".

Visual Studio 2019 also allows you to open the CMake directory directly. Choose "File->Open->CMake" for this option.

**macOS Xcode:**

For generating an Xcode workspace type:
```bash
cd build
cmake .. -G "Xcode"
```
Then open the generated work space in Xcode.

For generating Makefiles with optional non-default compilers, use the following commands:

```bash
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc-13 -DCMAKE_CXX_COMPILER=g++-13
```
In this example the brew installed GCC 13 is used for a release build.

**Linux**

For generating Linux Release Makefile:
```bash
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
```
For generating Linux Debug Makefile:
```bash
cd build
cmake .. -DCMAKE_BUILD_TYPE=Debug
```

Then type
```bash
make -j
```

For more details, refer to the CMake documentation: https://cmake.org/cmake/help/latest/

Build instructions for make
---------------------------

Open a command prompt on your system and change into the root directory of this project.

To use the default system compiler simply call:
```bash
make all
```


**MSYS2 and MinGW (Windows)**

**Note:** Build files for MSYS MinGW were added on request. The build platform is not regularily tested and can't be supported. 

Open an MSYS MinGW 64-Bit terminal and change into the root directory of this project.

Call:
```bash
make all
```

