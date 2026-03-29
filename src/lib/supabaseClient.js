/**
 * Supabase client for real-time subscriptions.
 * SUPABASE_URL and SUPABASE_ANON_KEY come from env vars (not service key — frontend only).
 */
import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://mxhzoqiilmwjofcawycm.supabase.co'
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im14aHpvcWlpbG13am9mY2F3eWNtIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQxOTk2MTQsImV4cCI6MjA4OTc3NTYxNH0.skelYZjzLpJ1wN3E6IOW2qSirVnvIe7qROOlP5gaZrc'

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
