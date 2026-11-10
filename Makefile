# NextSoftware2/Makefile
#
# How to build a single target:
#  make <project>-r  => build variant=release
#  make <project>-d  => build variant=debug
#  make <project>-p  => build variant=relwithdebinfo
#
# How to clean and build a single target:
#  make <project>-cr  => clean + build variant=release
#  make <project>-cd  => clean + build variant=debug
#  make <project>-cp  => clean + build variant=relwithdebinfo
#

TARGETS := CommonLib DecoderAnalyserApp DecoderAnalyserLib DecoderApp DecoderLib 
TARGETS += EncoderApp EncoderLib Utilities SEIRemovalApp StreamMergeApp


ifneq ($(verbose),)
CONFIG_OPTIONS += -DCMAKE_VERBOSE_MAKEFILE=ON
endif

ifneq ($(address-sanitizer),)
CONFIG_OPTIONS += -DNX2_USE_ADDRESS_SANITIZER=$(address-sanitizer)
endif

ifneq ($(thread-sanitizer),)
CONFIG_OPTIONS += -DNX2_USE_THREAD_SANITIZER=$(thread-sanitizer)
endif

ifneq ($(enable-werror),)
CONFIG_OPTIONS += -DNX2_ENABLE_WARNINGS_AS_WERROR=$(enable-werror)
endif

ifneq ($(osx-arch),)
CONFIG_OPTIONS += -DCMAKE_OSX_ARCHITECTURES=$(osx-arch)
endif

ifneq ($(toolchainfile),)
CONFIG_OPTIONS += -DCMAKE_TOOLCHAIN_FILE=$(toolchainfile)
endif

ifneq ($(enable-tracing),)
CONFIG_OPTIONS += -DNX2_ENABLE_TRACING=$(enable-tracing)
endif

ifneq ($(enable-lto),)
CONFIG_OPTIONS += -DNX2_ENABLE_LINK_TIME_OPT=$(enable-lto)
endif

ifeq ($(OS),Windows_NT)
  CMAKE_MCONFIG := 1
  CONFIG_PRESET := msvc-19.x
  BUILD_PRESET_RELEASE := msvc-19.x-r
  BUILD_PRESET_DEBUG := msvc-19.x-d
  BUILD_PRESET_RELWITHDEBINFO := msvc-19.x-rd
else
  UNAME_S := $(shell uname -s)
  ifeq ($(UNAME_S),Darwin)
    CMAKE_MCONFIG := 1
    CONFIG_PRESET := xcode
    BUILD_PRESET_RELEASE := xcode-r
    BUILD_PRESET_DEBUG := xcode-d
    BUILD_PRESET_RELWITHDEBINFO := xcode-rd
  endif
  ifeq ($(UNAME_S),Linux)
    CONFIG_PRESET_RELEASE := vscode-r
    CONFIG_PRESET_DEBUG := vscode-d
    CONFIG_PRESET_RELWITHDEBINFO := vscode-rd
    BUILD_PRESET_RELEASE := vscode-r
    BUILD_PRESET_DEBUG := vscode-d
    BUILD_PRESET_RELWITHDEBINFO := vscode-rd
  endif
endif

DEFAULT_BUILD_TARGETS_STATIC := release debug relwithdebinfo
DEFAULT_BUILD_TARGETS := $(DEFAULT_BUILD_TARGETS_STATIC)

ifeq ($(CMAKE_MCONFIG),)
release: configure-release
	cmake --build --preset $(BUILD_PRESET_RELEASE)

debug: configure-debug
	cmake --build --preset $(BUILD_PRESET_DEBUG)

relwithdebinfo: configure-relwithdebinfo
	cmake --build --preset $(BUILD_PRESET_RELWITHDEBINFO)
else
release: configure-static
	cmake --build --preset $(BUILD_PRESET_RELEASE)

debug: configure-static
	cmake --build --preset $(BUILD_PRESET_DEBUG)

relwithdebinfo: configure-static
	cmake --build --preset $(BUILD_PRESET_RELWITHDEBINFO)
endif

ifeq ($(CMAKE_MCONFIG),)
configure-release:
	cmake --preset $(CONFIG_PRESET_RELEASE) $(CONFIG_OPTIONS)

configure-debug:
	cmake --preset $(CONFIG_PRESET_DEBUG) $(CONFIG_OPTIONS)

configure-relwithdebinfo:
	cmake --preset $(CONFIG_PRESET_RELWITHDEBINFO) $(CONFIG_OPTIONS)

configure-static: $(foreach t,$(DEFAULT_BUILD_TARGETS_STATIC),configure-$(t))
else
configure-static:
	cmake --preset $(CONFIG_PRESET) $(CONFIG_OPTIONS)
endif

static: $(DEFAULT_BUILD_TARGETS_STATIC)

all: static

configure: configure-static

clean:
	$(RM) -rf build bin lib

realclean: clean
	$(RM) -rf install

distclean: realclean
	$(RM) -rf ext


# Some alias targets to ease interactive use in command shells
configure-r: configure-release
configure-d: configure-debug
configure-p: configure-relwithdebinfo

clean-r: clean-release
clean-d: clean-debug
clean-p: clean-relwithdebinfo

.PHONY: install

.NOTPARALLEL:
