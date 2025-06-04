#!/bin/sh
set -e

# configure ninfo_www settings.php
sed "s/SECRET_KEY = .*/SECRET_KEY = '${DJANGO_SECRET_KEY}'/" /app/ninfo_www/settings.py > tmp; cat tmp > /app/ninfo_www/settings.py; rm tmp
sed "s/DEBUG = .*/DEBUG = '${DJANGO_DEBUG}'/" /app/ninfo_www/settings.py > tmp; cat tmp > /app/ninfo_www/settings.py; rm tmp
sed "s/ALLOWED_HOSTS = .*/ALLOWED_HOSTS = ['${DJANGO_ALLOWED_HOSTS}']/" /app/ninfo_www/settings.py > tmp; cat tmp > /app/ninfo_www/settings.py; rm tmp
sed "s/CSRF_TRUSTED_ORIGINS = .*/CSRF_TRUSTED_ORIGINS = ['${DJANGO_ALLOWED_HOSTS}']/" /app/ninfo_www/settings.py > tmp; cat tmp > /app/ninfo_www/settings.py; rm tmp




echo "Running migrations..."
python manage.py migrate --noinput

echo "Checking for superuser..."

SUPERUSER_EXISTS=$(python manage.py shell -v 0 -c "from django.contrib.auth.models import User; print(User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists())")

if [ "$SUPERUSER_EXISTS" = "False" ]; then
    echo "Creating superuser..."
    python manage.py createsuperuser --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL --noinput
    echo "Superuser created."
fi

# Always set/update the password
echo "Setting superuser password..."
python manage.py shell -c "from django.contrib.auth.models import User; user = User.objects.get(username='$DJANGO_SUPERUSER_USERNAME'); user.set_password('$DJANGO_SUPERUSER_PASSWORD'); user.save()"
echo "Superuser password updated."

echo "Starting application as user $(id -u):$(id -g)..."
exec "$@"

