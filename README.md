🧱 Clonar e instalar

git clone https://github.com/leonardovila/financial-data-etl
cd financial-data-etl

🐍 Crear un entorno virtual

- Windows PowerShell:
python -m venv .venv
.venv\Scripts\activate

- Linux / macOS:
python -m venv .venv
source .venv/bin/activate

📦 Instalar el proyecto
pip install -e .

▶️ Ejecutar una corrida de ejemplo
python -m financial_data_etl.main_runner --assets NVDA