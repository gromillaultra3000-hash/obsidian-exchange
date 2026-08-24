<?php

namespace App\Http\Middleware;

use Closure;
use Filament\Facades\Filament;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

class RequireAdminMfa
{
    public function handle(Request $request, Closure $next): Response
    {
        $user = Filament::auth()->user();

        if ($user && (
            ! $user->canAccessPanel(Filament::getCurrentPanel())
            || ! $user->totp_secret
        )) {
            Filament::auth()->logout();
            $request->session()->invalidate();
            $request->session()->regenerateToken();

            return redirect()->to(Filament::getLoginUrl());
        }

        return $next($request);
    }
}
