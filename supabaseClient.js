const supabaseUrl = window.ENV.SUPABASE_URL;
const supabaseAnonKey = window.ENV.SUPABASE_KEY;

window.supabase = supabase.createClient(supabaseUrl, supabaseAnonKey);