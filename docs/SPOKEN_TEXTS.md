# Spoken alerts by text message (works while the phone is unlocked)

Jarvis sends you a normal text message for each announcement. An iPhone automation speaks every
text that starts with "Jarvis:", through your AirPods or the speaker, locked or unlocked.

> Free, but a bonus channel: it uses Verizon's email-to-text service, which Verizon is retiring by
> March 31, 2027 and which is sometimes slow. Telegram keeps working as normal.

## 1. Make a Gmail app password (3 min)
Jarvis sends the texts from your Gmail account.
1. In Safari, go to **myaccount.google.com/apppasswords** and sign in.
2. App name: `Jarvis`, then tap **Create**.
3. Copy the 16-letter password it shows (like `abcd efgh ijkl mnop`).

(This works because you turned on 2-step verification earlier. The app password can only send
email; revoke it on the same page any time.)

## 2. Connect it (1 min)
In Telegram, send your bot (the message is deleted right after):
```
/textsetup 5551234567 you@gmail.com abcd efgh ijkl mnop
```
Use your own 10-digit phone number, your Gmail address and the app password.
A **test text** starting with "Jarvis:" should arrive within a minute or two.
- **No text after 5 minutes?** Verizon is blocking it. Send `/textoff`, and Telegram stays as it is.

## 3. The speaking automation (3 min)
In **Shortcuts › Automation › + (New Automation)**:
1. Choose **Message**.
2. **Message Contains:** `Jarvis:`. Leave **Sender** empty (anyone).
3. Choose **Run Immediately**, and turn **Notify When Run** off. Tap **Next**.
4. **New Blank Automation** › add **Speak Text**. For the text, tap it and choose **Shortcut Input**
   (the message). Optionally expand it to pick a voice.
5. Tap **Done**.

## 4. Test
Send `/texttest` to your bot. When the text arrives, your phone should say it out loud, even if
you're using it at the time.

**Turn it off any time:** `/textoff`.
