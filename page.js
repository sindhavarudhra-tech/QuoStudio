import { supabase } from './supabaseClient' // Make sure the path points to your supabaseClient.js file

export default function TestPage() {

  // This is the test function we talked about
  async function testSupabaseConnection() {
    console.log("Testing Supabase connection...")
    
    const { data, error } = await supabase.auth.signUp({
      email: 'testuser123@example.com',
      password: 'securepassword123',
    })

    if (error) {
      console.error("❌ Connection failed:", error.message)
      alert("Check console: " + error.message)
    } else {
      console.log("✅ Connection successful! User created:", data)
      alert("Success! Check your browser console and Supabase table.")
    }
  }

  return (
    <div style={{ padding: "50px", textAlign: "center" }}>
      <h1>Quostudio Supabase Test</h1>
      <p>Click the button below to test your database and authentication connection:</p>
      
      {/* Clicking this button runs the test */}
      <button 
        onClick={testSupabaseConnection}
        style={{ padding: "10px 20px", fontSize: "16px", cursor: "pointer", background: "#000", color: "#fff", borderRadius: "5px" }}
      >
        Test Supabase Connection
      </button>
    </div>
  )
}