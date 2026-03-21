import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'

// Layout
import NavBar from './components/NavBar.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import CartButton from './components/CartButton.jsx'
import CartSidebar from './components/CartSidebar.jsx'

// Config
import { FEATURES } from './config/features.js'

// Pages
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Profile from './pages/Profile.jsx'
import Account from './pages/Account.jsx'
import MealPlans from './pages/MealPlans.jsx'
import Chat from './pages/Chat.jsx'
import ChefDashboard from './pages/ChefDashboard.jsx'
import ChefGallery from './pages/ChefGallery.jsx'
import ChefsDirectory from './pages/ChefsDirectory.jsx'
import PublicChef from './pages/PublicChef.jsx'
import CustomerOrders from './pages/CustomerOrders.jsx'
// HealthMetrics removed - health tracking deprecated
import Onboarding from './pages/Onboarding.jsx'
import EmailAuth from './pages/EmailAuth.jsx'
import VerifyEmail from './pages/VerifyEmail.jsx'
import MealPlanApproval from './pages/MealPlanApproval.jsx'
import Privacy from './pages/Privacy.jsx'
import Terms from './pages/Terms.jsx'
import RefundPolicy from './pages/RefundPolicy.jsx'
import AccessDenied from './pages/AccessDenied.jsx'
import NotFound from './pages/NotFound.jsx'
import GetReady from './pages/GetReady.jsx'
import PaymentSuccess from './pages/PaymentSuccess.jsx'
import PublicSurvey from './pages/PublicSurvey.jsx'

// Client Portal Pages (Multi-Chef Support)
import MyChefs from './pages/MyChefs.jsx'
import ChefHub from './pages/ChefHub.jsx'
import MyMealPlan from './pages/MyMealPlan.jsx'
import AllOrders from './pages/AllOrders.jsx'

// Chef Pages
import SousChefPage from './pages/SousChefPage.jsx'

export default function App(){
  return (
    <>
      <NavBar />
      <CartButton />
      <CartSidebar />
      <main id="main-content">
      <Routes>
        {/* Public routes */}
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/chefs" element={<ChefsDirectory />} />
        <Route path="/chefs/:username" element={<PublicChef />} />
        <Route path="/chefs/:username/gallery" element={<ChefGallery />} />
        {/* Short URL aliases for chef profiles */}
        <Route path="/c/:username" element={<PublicChef />} />
        <Route path="/c/:username/gallery" element={<ChefGallery />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="/refund-policy" element={<RefundPolicy />} />
        <Route path="/email-auth" element={<EmailAuth />} />
        <Route path="/payment-success" element={<PaymentSuccess />} />
        <Route path="/survey/:token" element={<PublicSurvey />} />
        <Route path="/403" element={<AccessDenied />} />

        {/* Protected routes - require authentication */}
        <Route path="/profile" element={
          <ProtectedRoute>
            <Profile />
          </ProtectedRoute>
        } />
        <Route path="/account" element={
          <ProtectedRoute>
            <Account />
          </ProtectedRoute>
        } />
        <Route path="/verify-email" element={
          <ProtectedRoute>
            <VerifyEmail />
          </ProtectedRoute>
        } />
        <Route path="/onboarding" element={
          <ProtectedRoute>
            <Onboarding />
          </ProtectedRoute>
        } />
        {/* Health metrics removed - redirect to profile */}
        <Route path="/health-metrics" element={<Navigate to="/profile" replace />} />
        <Route path="/health" element={<Navigate to="/profile" replace />} />
        
        {/* Chef Preview Mode - for users without chef access */}
        <Route path="/get-ready" element={
          <ProtectedRoute>
            <GetReady />
          </ProtectedRoute>
        } />

        {/* =================================================================== */}
        {/* Client Portal Routes (Multi-Chef Support) */}
        {/* =================================================================== */}
        
        {/* My Chefs - list of connected chefs (with smart redirect for single chef) */}
        <Route path="/my-chefs" element={
          <ProtectedRoute requiredRole="customer">
            <MyChefs />
          </ProtectedRoute>
        } />
        
        {/* Individual Chef Hub */}
        <Route path="/my-chefs/:chefId" element={
          <ProtectedRoute requiredRole="customer">
            <ChefHub />
          </ProtectedRoute>
        } />
        
        {/* Chef-specific Meal Plan View */}
        <Route path="/my-chefs/:chefId/meal-plan" element={
          <ProtectedRoute requiredRole="customer">
            <MyMealPlan />
          </ProtectedRoute>
        } />
        
        {/* Chef-specific Orders (redirect to AllOrders with filter) */}
        <Route path="/my-chefs/:chefId/orders" element={
          <ProtectedRoute requiredRole="customer">
            <AllOrders />
          </ProtectedRoute>
        } />
        
        {/* Legacy redirect: /my-chef -> /my-chefs */}
        <Route path="/my-chef" element={<Navigate to="/my-chefs" replace />} />

        {/* =================================================================== */}
        {/* Customer-specific routes */}
        {/* =================================================================== */}
        
        {/* Unified Orders page (all chefs) - shows both service orders and meal orders */}
        <Route path="/orders" element={
          <ProtectedRoute requiredRole="customer">
            <CustomerOrders />
          </ProtectedRoute>
        } />
        
        {/* Legacy Meal Plans (behind feature flag, or redirect) */}
        <Route path="/meal-plans" element={
          <ProtectedRoute requiredRole="customer">
            {FEATURES.CUSTOMER_STANDALONE_MEAL_PLANS ? (
              <MealPlans />
            ) : (
              <Navigate to="/my-chefs" replace />
            )}
          </ProtectedRoute>
        } />
        
        {/* Legacy Chat (behind feature flag) */}
        <Route path="/chat" element={
          <ProtectedRoute requiredRole="customer">
            {FEATURES.CUSTOMER_AI_CHAT ? (
              <Chat />
            ) : (
              <Navigate to="/my-chefs" replace />
            )}
          </ProtectedRoute>
        } />
        
        {/* Legacy Customer Orders (redirect to new AllOrders) */}
        <Route path="/customer-orders" element={
          <Navigate to="/orders" replace />
        } />
        
        <Route path="/meal-plan-approval" element={
          <ProtectedRoute requiredRole="customer">
            <MealPlanApproval />
          </ProtectedRoute>
        } />

        {/* Chef-specific routes */}
        <Route path="/chefs/dashboard" element={
          <ProtectedRoute requiredRole="chef">
            <ChefDashboard />
          </ProtectedRoute>
        } />
        
        {/* Sous Chef Full Page View */}
        <Route path="/chefs/dashboard/sous-chef" element={
          <ProtectedRoute requiredRole="chef">
            <SousChefPage />
          </ProtectedRoute>
        } />

        {/* 404 catch-all */}
        <Route path="*" element={<NotFound />} />
      </Routes>
      </main>
    </>
  )
}
