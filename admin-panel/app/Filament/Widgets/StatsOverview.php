<?php

namespace App\Filament\Widgets;

use App\Models\Order;
use Filament\Widgets\StatsOverviewWidget as BaseWidget;
use Filament\Widgets\StatsOverviewWidget\Stat;

class StatsOverview extends BaseWidget
{
    protected function getStats(): array
    {
        $total = Order::count();
        $pending = Order::where('status', 'pending')->count();
        $sent = Order::where('status', 'sent')->count();
        $volume = Order::where('status', 'sent')->sum('rub_amount');

        return [
            Stat::make('Всего заявок', $total),
            Stat::make('Ожидают', $pending)
                ->color('warning'),
            Stat::make('Выполнено', $sent)
                ->color('success'),
            Stat::make('Оборот (RUB)', number_format($volume, 0, '.', ' ')),
        ];
    }
}
