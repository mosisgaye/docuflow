import { test } from 'node:test'
import assert from 'node:assert/strict'
import { signer } from '../src/index.js'

test('la signature se vérifie avec la clé publique', async () => {
  const paire = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify'])
  const privee = Buffer.from(await crypto.subtle.exportKey('pkcs8', paire.privateKey)).toString('base64')
  const corps = new TextEncoder().encode('From: a@b\r\n\r\ncorps')

  const signature = await signer(privee, '1000', corps)

  const message = new TextEncoder().encode('1000.From: a@b\r\n\r\ncorps')
  assert.ok(await crypto.subtle.verify({ name: 'Ed25519' }, paire.publicKey, Buffer.from(signature, 'base64'), message))
})
