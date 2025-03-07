#!/usr/bin/env python

import os.path
from glob import glob
from os.path import basename, splitext

from setuptools import find_packages, setup


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


with open("requirements.txt") as f:
    required = f.read().splitlines()


long_description = read("Readme.rst")

setup(
    name="porepy",
    version="1.7.0",
    license="GPL",
    keywords=["porous media simulation fractures deformable"],
    install_requires=required,
    description="Simulation tool for fractured and deformable porous media",
    long_description=long_description,
    maintainer="Eirik Keilegavlen",
    maintainer_email="Eirik.Keilegavlen@uib.no",
    platforms=["Linux", "Windows", "Mac OS-X"],
    package_data={"porepy": ["py.typed"]},
    packages=find_packages("src"),
    package_dir={"": "src"},
    py_modules=[
        os.path.splitext(os.path.basename(path))[0] for path in glob("src/*.py")
    ],
    zip_safe=False,
)
