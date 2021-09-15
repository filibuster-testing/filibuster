.PHONY: install dist

install:
	python3 setup.py develop

dist:
	python3 setup.py sdist bdist_wheel
