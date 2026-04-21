from setuptools import setup

import os

# Read requirements.txt
def read_requirements():
    with open("requirements.txt") as f:
        return f.read().splitlines()
        
setup(
    name='tcspy',
    version='1.0.5',
    packages=['tcspy'],
    package_dir={'tcspy': '.'},
    author='Hyeonho Choi',
    description='Telescope Control System with python',
    long_description=open('README.md').read() if os.path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    url='https://github.com/hhchoi1022/tippy',  # optional
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.8',
    install_requires=read_requirements(),  # This uses your requirements.txt
)
