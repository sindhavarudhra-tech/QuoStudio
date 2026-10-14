// Client-End-to-End Encryption Utility using Web Crypto API
class CryptoManager {
    async deriveKey(passphrase, salt) {
        const enc = new TextEncoder();
        const keyMaterial = await window.crypto.subtle.importKey(
            "raw",
            enc.encode(passphrase),
            { name: "PBKDF2" },
            false,
            ["deriveKey"]
        );
        return window.crypto.subtle.deriveKey(
            {
                name: "PBKDF2",
                salt: enc.encode(salt),
                iterations: 100000,
                hash: "SHA-256"
            },
            keyMaterial,
            { name: "AES-GCM", length: 256 },
            false,
            ["encrypt", "decrypt"]
        );
    }

    async encryptData(plaintext, passphrase, salt = "QuoStudioSecureSalt") {
        const key = await this.deriveKey(passphrase, salt);
        const iv = window.crypto.getRandomValues(new Uint8Array(12));
        const encoded = new TextEncoder().encode(JSON.stringify(plaintext));

        const ciphertext = await window.crypto.subtle.encrypt(
            { name: "AES-GCM", iv: iv },
            key,
            encoded
        );

        // Combine IV and Ciphertext for storage
        const combined = new Uint8Array(iv.byteLength + ciphertext.byteLength);
        combined.set(iv, 0);
        combined.set(new Uint8Array(ciphertext), iv.byteLength);

        return btoa(String.fromCharCode(...combined));
    }

    async decryptData(base64Ciphertext, passphrase, salt = "QuoStudioSecureSalt") {
        try {
            const key = await this.deriveKey(passphrase, salt);
            const combined = Uint8Array.from(atob(base64Ciphertext), c => c.charCodeAt(0));

            const iv = combined.slice(0, 12);
            const ciphertext = combined.slice(12);

            const decrypted = await window.crypto.subtle.decrypt(
                { name: "AES-GCM", iv: iv },
                key,
                ciphertext
            );

            return JSON.parse(new TextDecoder().decode(decrypted));
        } catch (e) {
            console.error("Decryption failed. Incorrect passphrase or corrupted data.");
            return null;
        }
    }
}