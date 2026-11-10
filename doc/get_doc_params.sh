#/!bin/bash

cat software-manual.tex  | grep '\\Option' | sed -e "s/\\\Option{//" | sed -e "s/}.*//" | sort | uniq  > ../../encoder_params_doc.txt
