from setuptools import setup, find_packages

setup(
    name="ollm",
    version="1.0.0",
    description="Minimalist, high-efficiency offline LLM CLI with recursive tool execution",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "llama-cpp-python>=0.3.0",
    ],
    entry_points={
        "console_scripts": [
            "ollm=ollm.cli:main",
            "lm=ollm.cli:main",
        ],
    },
)
