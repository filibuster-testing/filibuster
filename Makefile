.PHONY: install dist test-push push

install:
	python3 setup.py develop

dist:
	python3 setup.py sdist bdist_wheel

test-push:
	twine upload --repository testpypi --skip-existing dist/*

push:
	twine upload --repository pypi --skip-existing dist/*