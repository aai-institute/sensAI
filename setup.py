import functools
import re
from typing import Iterable, Dict
from glob import glob

from setuptools import setup, find_namespace_packages

tf_requirements = ['tensorflow==1.15.0']
torch_requirements = ['torch==1.4.0', 'torchtext==0.5.0']
lightgbm_requirements = ['lightgbm==2.3.0']
geoanalytics_requirements = ['networkx==2.4', 'Shapely~=1.7.0', 'geopandas==0.7.0', 'utm==0.7.0']


# list of dependencies where ==/~= dependencies (used in requirements.txt and for the extras in requirements_*.txt) are relaxed:
# any later version is OK (as long as we are not aware of a concrete limitation - and once we are, we shall define
# the respective upper bound below)
DEPS_VERSION_LOWER_BOUND = [
    # main
    "pandas", "scipy", "numpy", "scikit-learn", "seaborn", "typing-extensions",
    # extra "torch"
    "torch", "torchtext",
    # extra "tensorflow"
    "tensorflow",
    # extra "lightgbm"
    "lightgbm",
    # extra "geoanalytics"
    "networkx", "Shapely", "geopandas", "utm",
]
# upper bound: map dependency name to lowest exluded version
DEPS_VERSION_UPPER_BOUND_EXCLUSIVE: Dict[str, str] = {}


def relaxed_requirements(deps: Iterable[str]):
    """
    :param deps: the set of requirements
    :return: the set of updated requirements with the relaxations defined above applied
    """
    updated_deps = []
    for dep in deps:
        dep = dep.strip()
        if dep.startswith("#"):
            continue
        m = re.match(r'([\w-]+)[=~]=', dep)  # match package with == or ~= version spec
        if m:
            package = m.group(1)
            if package in DEPS_VERSION_LOWER_BOUND:
                dep = dep.replace("==", ">=").replace("~=", ">=")
            elif package in DEPS_VERSION_UPPER_BOUND_EXCLUSIVE:
                dep = dep.replace("==", ">=").replace("~=", ">=")
                dep += ",<" + DEPS_VERSION_UPPER_BOUND_EXCLUSIVE[package]
        updated_deps.append(dep)
    return updated_deps


def relaxed_requirements_from_file(path):
    with open(path, "r") as f:
        return relaxed_requirements(f.readlines())


# create extras requirements from requirements_*.txt, and add "full" extras which combines them all
extras_require = {}
for extras_requirements_file in glob("requirements_*.txt"):
    m = re.match(r"requirements_(\w+).txt", extras_requirements_file)
    extra_name = m.group(1)
    extras_require[extra_name] = relaxed_requirements_from_file(extras_requirements_file)
extras_require["full"] = functools.reduce(lambda x, y: x + y, list(extras_require.values()))


setup(
    name='sensai',
    package_dir={"": "src"},
    license="MIT",
    url="https://github.com/jambit/sensAI",
    packages=find_namespace_packages(where="src"),
    include_package_data=True,
    version='0.1.9.dev0',
    description='Library for sensible AI',
    install_requires=relaxed_requirements_from_file("requirements.txt"),
    dependency_links=["https://download.pytorch.org/whl/torch_stable.html"],
    setup_requires=["wheel"],
    extras_require=extras_require,
    author='jambit GmbH'
)
