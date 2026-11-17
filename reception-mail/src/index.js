// Worker Cloudflare branché sur l'adresse de dépôt des factures.
//
// Il ne lit pas le mail : il le transmet BRUT, tel que reçu, à POST /reception/mail,
// signé avec sa clé privée Ed25519. C'est Verifac qui analyse le mail (moteur/reception_mail.py),
// comme il le fera pour les mails venus de Microsoft 365, de Gmail ou d'IMAP.
//
// Liaisons (bindings) :
//   DOCUFLOW_URL         adresse publique de l'API, sans / final
//   DOCUFLOW_CLE_PRIVEE  clé privée Ed25519 au format PKCS#8, en base64 (secret chiffré,
//                        créée chez Cloudflare, n'en sort jamais)
//
// Si Verifac refuse ou ne répond pas, le mail est rejeté : l'expéditeur reçoit un message
// d'erreur et sait qu'il doit renvoyer sa facture. Aucun mail n'est perdu en silence.

const TAILLE_MAX_OCTETS = 25 * 1024 * 1024 // limite d'Email Routing
const DELAI_MAX_MS = 20_000

function versOctets(base64) {
  const texte = atob(base64)
  const octets = new Uint8Array(texte.length)
  for (let i = 0; i < texte.length; i++) octets[i] = texte.charCodeAt(i)
  return octets
}

function versBase64(octets) {
  let texte = ''
  for (let i = 0; i < octets.length; i += 0x8000) texte += String.fromCharCode(...octets.subarray(i, i + 0x8000))
  return btoa(texte)
}

/** Signature de « horodatage.corps », en base64, telle que Verifac la vérifie. */
export async function signer(clePriveeBase64, horodatage, corps) {
  const cle = await crypto.subtle.importKey('pkcs8', versOctets(clePriveeBase64), { name: 'Ed25519' }, false, ['sign'])
  const prefixe = new TextEncoder().encode(`${horodatage}.`)
  const message = new Uint8Array(prefixe.length + corps.length)
  message.set(prefixe)
  message.set(corps, prefixe.length)
  return versBase64(new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, cle, message)))
}

/** Envoie le mail brut (Uint8Array) à Verifac. */
export async function transmettre(env, brut, maintenant = Date.now()) {
  const horodatage = String(Math.floor(maintenant / 1000))
  return fetch(`${env.DOCUFLOW_URL}/reception/mail`, {
    method: 'POST',
    headers: {
      'Content-Type': 'message/rfc822',
      'X-DocuFlow-Horodatage': horodatage,
      'X-DocuFlow-Signature': await signer(env.DOCUFLOW_CLE_PRIVEE, horodatage, brut),
    },
    body: brut,
    signal: AbortSignal.timeout(DELAI_MAX_MS),
  })
}

export default {
  async email(message, env) {
    if (message.rawSize > TAILLE_MAX_OCTETS) {
      message.setReject('Mail trop volumineux pour Verifac (25 Mo au maximum).')
      return
    }
    try {
      const brut = new Uint8Array(await new Response(message.raw).arrayBuffer())
      const reponse = await transmettre(env, brut)
      console.log(JSON.stringify({ de: message.from, statut: reponse.status, reponse: (await reponse.text()).slice(0, 500) }))
      if (!reponse.ok) message.setReject(`Verifac a refusé ce mail (code ${reponse.status}). Renvoyez la facture plus tard.`)
    } catch (erreur) {
      console.error('Transmission impossible :', String(erreur))
      message.setReject('Verifac est momentanément indisponible. Renvoyez la facture plus tard.')
    }
  },
}
