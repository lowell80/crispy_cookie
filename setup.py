#!/usr/bin/env python

"""The setup script."""

from setuptools import find_packages, setup

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

with open('requirements.txt') as requirements_file:
    requirements = requirements_file.readlines()

setup_requirements = []

test_requirements = []

setup(
    author="Lowell Alleman",
    author_email='lowell87@gmail.com',
    python_requires='>=3.6',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
    description="Splunk app boilerplate builder that uses a combination of Cookiecutter and Ksconf layers.",
    entry_points={
        'console_scripts': [
            'crispy_cookie=crispy_cookie.cli:main',
        ],
    },
    install_requires=requirements,
    license="Apache Software License 2.0",
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='crispy_cookie',
    name='crispy_cookie',
    packages=find_packages(include=['crispy_cookie', 'crispy_cookie.*']),
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/lowell80/crispy_cookie',
    version='0.6.3',
    zip_safe=False,
)
