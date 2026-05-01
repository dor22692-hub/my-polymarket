#!/bin/bash
# Polymarket VPS Setup — Hostinger
set -e

echo "=== מתקין Python ו-Git ==="
apt-get update -qq
apt-get install -y python3 python3-pip git cron

echo "=== מוריד את הקוד מ-GitHub ==="
cd /root
rm -rf polymarket
git clone https://github.com/dor22692-hub/my-polymarket.git polymarket
cd polymarket

echo "=== מתקין תלויות ==="
pip3 install httpx requests pandas loguru pydantic pydantic-settings python-dotenv tenacity

echo "=== מגדיר משתני סביבה ==="
cat > /root/polymarket/.env << 'ENVEOF'
SUPABASE_URL=https://mncvhthgeqsfxkriskhk.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1uY3ZodGhnZXFzZnhrcmlza2hrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc2MzE0MDgsImV4cCI6MjA5MzIwNzQwOH0.WQZ4zkOjzeXQaoKYfmQXdU-kpBdUBx3dPPNiKR8dkMY
ENVEOF

echo "=== מריץ סריקה ראשונה ==="
cd /root/polymarket
python3 main.py

echo "=== מגדיר cron — סריקה כל שעה ==="
(crontab -l 2>/dev/null; echo "0 * * * * cd /root/polymarket && python3 main.py >> /var/log/polymarket.log 2>&1") | crontab -
service cron start || systemctl start cron

echo ""
echo "✅ הגדרה הושלמה! הסריקה תרוץ כל שעה אוטומטית."
echo "לוג: tail -f /var/log/polymarket.log"
