<?php

namespace App\Filament\Resources\PayoutQueueResource\Pages;

use App\Filament\Resources\PayoutQueueResource;
use Filament\Resources\Pages\ListRecords;

class ListPayoutQueues extends ListRecords
{
    protected static string $resource = PayoutQueueResource::class;

    protected function getHeaderActions(): array
    {
        return [];
    }
}
