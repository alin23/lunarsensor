import uvicorn

from lunarsensor import app

uvicorn.run(app, host='0.0.0.0')
