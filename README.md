# 🚀 BoomGuru

BoomGuru analyzes **machine-related images using LLM** and returns possible **failure or issue predictions** in text format.

---

## 📦 Project Structure

```
BOOM_GURU/
├── files/                  # Input/output or temporary files
├── logs/                   # Buraya yaz
├── src/                    # Buraya yaz
├── prompts/                # LLM prompt templates
├── venv/                   # Virtual environment (excluded from git)
├── .env                    # Local environment variables (excluded from git)
├── .env.example            # Example environment file for setup
├── boomguru.service.example# Example systemd unit file
├── listener_app.py         # Optional listener logic (for test purposes)
├── main.py                 # Main production entry point
├── requirements.txt        # Dependencies
└── README.md               # This document
```

---

## ⚙️ Setup

### 1) Clone the repository and prepare the environment

```bash
git clone https://<your-repo-url>.git
cd BOOM_GURU
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit your environment values
```

> Fill in the required keys and credentials in the `.env` file.

---

## 🧩 Systemd Service Setup (Production)

### 1) Copy the service file

```bash
sudo cp boomguru.service.example /etc/systemd/system/boomguru.service
```

Then open it and edit paths or user information if needed:

```bash
sudo nano /etc/systemd/system/boomguru.service
```

### 2) Reload daemon and enable service

```bash
sudo systemctl daemon-reload
sudo systemctl enable boomguru.service
```

### 3) Start the service

```bash
sudo systemctl start boomguru.service
```

---

## 🛠️ Service Management

Check service status:

```bash
sudo systemctl status boomguru.service
```

Restart or stop the service:

```bash
sudo systemctl restart boomguru.service
sudo systemctl stop boomguru.service
```

View live logs:

```bash
sudo journalctl -u boomguru.service -f
```

> If you modify the unit file:

```bash
sudo systemctl daemon-reload
sudo systemctl restart boomguru.service
```
