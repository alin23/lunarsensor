all: install run
	
install:
	pip install -r requirements.txt

run:
	sudo uvicorn --host 0.0.0.0 --port 80 --reload lunarsensor:app
