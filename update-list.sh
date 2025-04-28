#!/bin/sh

./gen-member-list.py || exit 1;

ARK_OUT_DIR="../build" ark build || exit 1;

exit 0;