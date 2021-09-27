from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()
with open("requirements.txt", "r") as fh:
    requirements = fh.read()
setup(
    name='filibuster',
    version='0.0.4',
    author='Christopher S. Meiklejohn',
    author_email='christopher.meiklejohn@gmail.com',
    license='Apache-2.0',
    description='Filibuster CLI tool and Python client libraries.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://www.github.com/filibuster-testing/filibuster',
    py_modules=['filibuster'],
    packages=find_packages(),
    install_requires=[requirements],
    python_requires='>=3.7',
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "Operating System :: OS Independent",
    ],
    entry_points={
        "console_scripts": [
            "filibuster = filibuster_cli:test",
            "filibuster-analysis = filibuster_analysis_cli:analyze",
            "filibuster-loadgen = filibuster_loadgen_cli:loadgen",
            "filibuster-coverage = filibuster_coverage_cli:coverage"
        ]
    },
)
