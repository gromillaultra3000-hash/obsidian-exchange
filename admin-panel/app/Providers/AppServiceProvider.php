<?php

namespace App\Providers;

use App\Support\AdminAudit;
use Illuminate\Support\Facades\Event;
use Illuminate\Support\ServiceProvider;

class AppServiceProvider extends ServiceProvider
{
    /**
     * Register any application services.
     */
    public function register(): void
    {
        //
    }

    /**
     * Bootstrap any application services.
     */
    public function boot(): void
    {
        foreach (['created', 'updated', 'deleted'] as $event) {
            Event::listen("eloquent.{$event}: *", function (string $name, array $payload) use ($event): void {
                if (($payload[0] ?? null) instanceof \Illuminate\Database\Eloquent\Model) {
                    AdminAudit::record($event, $payload[0]);
                }
            });
        }
    }
}
