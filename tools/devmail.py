"""Serveur SMTP de TEST (local, hors production).

Demarre un faux serveur SMTP sur localhost:1025 qui n'envoie rien : il affiche
simplement les messages recus (expediteur, destinataires, sujet, corps). Permet
de tester l'envoi de Sentinelle sans etre sur le reseau de l'entreprise.

Usage :
    python tools/devmail.py

Puis dans Sentinelle > Preferences > SMTP :
    Serveur = localhost   Port = 1025   Utilisateur/Mot de passe = vides
et lancer "Test d'envoi". Le mail s'affiche dans cette fenetre.
"""
import sys
import asyncio
from email.parser import BytesParser
from email.policy import default as default_policy

try:
    # affichage immediat + UTF-8 (sinon les accents s'affichent mal en console)
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

HOST, PORT = 'localhost', 1025


async def handle(reader, writer):
    async def send(line):
        writer.write((line + '\r\n').encode())
        await writer.drain()

    async def read_line():
        return (await reader.readline()).decode(errors='replace').rstrip('\r\n')

    await send('220 devmail SMTP de test')
    data_lines = []
    in_data = False
    while True:
        line = await read_line()
        if line == '' and not in_data:
            break
        if in_data:
            if line == '.':
                in_data = False
                raw = ('\r\n'.join(data_lines)).encode('utf-8', 'replace')
                _print_message(raw)
                data_lines = []
                await send('250 OK: message recu')
            else:
                data_lines.append(line[1:] if line.startswith('..') else line)
            continue

        cmd = line.upper()
        if cmd.startswith(('EHLO', 'HELO')):
            await send('250 devmail')          # aucune extension -> pas de STARTTLS
        elif cmd.startswith('MAIL'):
            await send('250 OK')
        elif cmd.startswith('RCPT'):
            await send('250 OK')
        elif cmd.startswith('DATA'):
            in_data = True
            await send('354 Envoyez le message, terminez par <CRLF>.<CRLF>')
        elif cmd.startswith(('RSET', 'NOOP')):
            await send('250 OK')
        elif cmd.startswith('QUIT'):
            await send('221 Au revoir')
            break
        else:
            await send('250 OK')
    writer.close()


def _print_message(raw):
    msg = BytesParser(policy=default_policy).parsebytes(raw)
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                body = part.get_content()
                break
    else:
        body = msg.get_content()
    print('\n' + '=' * 70)
    print('MAIL RECU')
    print('  De      :', msg['From'])
    print('  A       :', msg['To'])
    print('  Sujet   :', msg['Subject'])
    print('  Corps   :')
    for l in (body or '').splitlines():
        print('    ' + l)
    has_html = any(p.get_content_type() == 'text/html' for p in msg.walk()) \
        if msg.is_multipart() else False
    print('  HTML    :', 'oui' if has_html else 'non')
    print('=' * 70 + '\n')


async def main():
    server = await asyncio.start_server(handle, HOST, PORT)
    print(f"Serveur SMTP de test demarre sur {HOST}:{PORT} (Ctrl+C pour arreter)")
    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\nArret.')
