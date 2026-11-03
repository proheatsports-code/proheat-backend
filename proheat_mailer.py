"""Envio de correos transaccionales de ProHeat Sports."""

import os
import smtplib
import ssl

from email.message import EmailMessage


def mail_configured():
    required = (
        "PROHEAT_SMTP_HOST",
        "PROHEAT_SMTP_PORT",
        "PROHEAT_SMTP_USER",
        "PROHEAT_SMTP_PASSWORD",
        "PROHEAT_SMTP_FROM",
    )

    return all(os.environ.get(key) for key in required)


def send_password_reset_email(recipient, code):
    """Envia un codigo de recuperacion sin registrarlo en logs."""

    if not mail_configured():
        raise RuntimeError("Servicio de correo no configurado")

    host = os.environ["PROHEAT_SMTP_HOST"]
    port = int(os.environ["PROHEAT_SMTP_PORT"])
    username = os.environ["PROHEAT_SMTP_USER"]
    password = os.environ["PROHEAT_SMTP_PASSWORD"]
    sender = os.environ["PROHEAT_SMTP_FROM"]

    message = EmailMessage()
    message["Subject"] = "Recuperacion de cuenta - ProHeat Sports"
    message["From"] = sender
    message["To"] = recipient

    message.set_content(
        "Recibimos una solicitud para recuperar tu cuenta "
        "de ProHeat Sports.\n\n"
        f"Tu codigo de verificacion es: {code}\n\n"
        "Este codigo caduca en 15 minutos y solo puede "
        "utilizarse una vez.\n\n"
        "Si no solicitaste este cambio, ignora este correo."
    )

    context = ssl.create_default_context()

    if port == 465:
        with smtplib.SMTP_SSL(
            host, port, timeout=15, context=context
        ) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)

    elif port == 587:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)

    else:
        raise ValueError(
            "Puerto SMTP no admitido. Utiliza 465 o 587."
        )

    return True
